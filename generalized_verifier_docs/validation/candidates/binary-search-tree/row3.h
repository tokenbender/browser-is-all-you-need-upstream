#if !defined(BINARY_SEARCH_TREE_H)
#define BINARY_SEARCH_TREE_H

#include <memory>

namespace binary_search_tree {

struct Node {
    int data;
    std::shared_ptr<Node> left;
    std::shared_ptr<Node> right;
};

class BinarySearchTree {
public:
    BinarySearchTree();
    ~BinarySearchTree();

    void insert(int data);
    bool search(int data);

private:
    std::shared_ptr<Node> root;

    void _insert(std::shared_ptr<Node> node, int data);
    bool _search(std::shared_ptr<Node> node, int data);
};

}  // namespace binary_search_tree

#endif // BINARY_SEARCH_TREE_H
