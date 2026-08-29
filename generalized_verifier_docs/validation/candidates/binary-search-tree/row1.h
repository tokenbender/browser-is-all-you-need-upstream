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
    void insert(int data);
    bool contains(int data) const;

private:
    Node* root_;
    void insert(Node*& node, int data);
    bool contains(Node* node, int data) const;
};

}  // namespace binary_search_tree

#endif // BINARY_SEARCH_TREE_H
