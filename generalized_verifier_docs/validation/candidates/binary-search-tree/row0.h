#if !defined(BINARY_SEARCH_TREE_H)
#define BINARY_SEARCH_TREE_H

namespace binary_search_tree {

struct Node {
    int data;
    Node* left;
    Node* right;
};

class BinarySearchTree {
public:
    BinarySearchTree();
    ~BinarySearchTree();
    void insert(int data);
    bool search(int data);

private:
    Node* root_;
    void _insert(Node* node, int data);
    bool _search(Node* node, int data);
    void _destroy(Node* node);
};

}  // namespace binary_search_tree

#endif // BINARY_SEARCH_TREE_H
